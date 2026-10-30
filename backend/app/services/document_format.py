import copy
from lxml import etree
from fastapi import HTTPException

WORD = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
TEXT = 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'
OFFICE = 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
STYLE = 'urn:oasis:names:tc:opendocument:xmlns:style:1.0'
FO = 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'


def part(document, name, tag):
    if name in document.format_parts:
        return document.format_parts[name]
    if name in document.archive.namelist():
        if document.archive.getinfo(name).file_size > 2 * 1024 * 1024:
            raise HTTPException(413, 'Document formatting is too complex')
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        tree = etree.fromstring(document.archive.read(name), parser)
        if tree.getroottree().docinfo.doctype or any(isinstance(node, etree._Entity) for node in tree.iter()):
            raise HTTPException(415, 'Unsupported document formatting')
    else:
        tree = etree.Element(tag)
    document.format_parts[name] = tree
    return tree


def property_node(parent, tag):
    node = parent.find(tag)
    if node is None:
        node = etree.Element(tag)
        parent.insert(0, node)
    return node


def word_number(document, style):
    if style in document.list_ids:
        return document.list_ids[style]
    root = part(document, 'word/numbering.xml', f'{{{WORD}}}numbering')
    abstract_id = max([int(node.get(f'{{{WORD}}}abstractNumId', '0')) for node in root.findall(f'{{{WORD}}}abstractNum')] + [-1]) + 1
    num_id = max([int(node.get(f'{{{WORD}}}numId', '0')) for node in root.findall(f'{{{WORD}}}num')] + [0]) + 1
    abstract = etree.Element(f'{{{WORD}}}abstractNum', {f'{{{WORD}}}abstractNumId': str(abstract_id)})
    level = etree.SubElement(abstract, f'{{{WORD}}}lvl', {f'{{{WORD}}}ilvl': '0'})
    for name, value in [('start', '1'), ('numFmt', 'bullet' if style == 'bullet' else 'decimal'), ('lvlText', '•' if style == 'bullet' else '%1.'), ('lvlJc', 'left')]:
        etree.SubElement(level, f'{{{WORD}}}{name}', {f'{{{WORD}}}val': value})
    properties = etree.SubElement(level, f'{{{WORD}}}pPr')
    etree.SubElement(properties, f'{{{WORD}}}ind', {f'{{{WORD}}}left': '720', f'{{{WORD}}}hanging': '360'})
    numbers = root.findall(f'{{{WORD}}}num')
    root.insert(root.index(numbers[0]) if numbers else len(root), abstract)
    number = etree.SubElement(root, f'{{{WORD}}}num', {f'{{{WORD}}}numId': str(num_id)})
    etree.SubElement(number, f'{{{WORD}}}abstractNumId', {f'{{{WORD}}}val': str(abstract_id)})
    relationships = part(document, 'word/_rels/document.xml.rels', f'{{{REL}}}Relationships')
    relation_type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering'
    existing = next((node for node in relationships if node.get('Type') == relation_type), None)
    if existing is not None and existing.get('Target') != 'numbering.xml':
        raise HTTPException(415, 'This document uses a custom numbering part')
    if existing is None:
        identifiers = {node.get('Id') for node in relationships}
        identifier = 'rootdriveNumbering'
        while identifier in identifiers:
            identifier += '1'
        etree.SubElement(relationships, f'{{{REL}}}Relationship', Id=identifier, Type=relation_type, Target='numbering.xml')
    types = part(document, '[Content_Types].xml', f'{{{CT}}}Types')
    if not any(node.get('PartName') == '/word/numbering.xml' for node in types):
        etree.SubElement(types, f'{{{CT}}}Override', PartName='/word/numbering.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml')
    document.modified_parts.update({'word/numbering.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'})
    document.list_ids[style] = str(num_id)
    return str(num_id)


def format_info(document, node):
    result = {'bold': False, 'italic': False, 'style': 'body'}
    if document.word:
        runs = list(node.iter(f'{{{WORD}}}r'))
        for key, name in [('bold', 'b'), ('italic', 'i')]:
            result[key] = bool(runs) and all((value := run.find(f'{{{WORD}}}rPr/{{{WORD}}}{name}')) is not None and value.get(f'{{{WORD}}}val', '1') not in {'0', 'false', 'off'} for run in runs)
        style = node.find(f'{{{WORD}}}pPr/{{{WORD}}}pStyle')
        if style is not None and style.get(f'{{{WORD}}}val', '').lower().startswith('heading'):
            result['style'] = 'heading2' if style.get(f'{{{WORD}}}val', '').endswith('2') else 'heading1'
        number = node.find(f'{{{WORD}}}pPr/{{{WORD}}}numPr/{{{WORD}}}numId')
        if number is not None and number.get(f'{{{WORD}}}val') != '0':
            root = part(document, 'word/numbering.xml', f'{{{WORD}}}numbering')
            value = number.get(f'{{{WORD}}}val')
            instance = next((item for item in root.findall(f'{{{WORD}}}num') if item.get(f'{{{WORD}}}numId') == value), None)
            abstract = instance.find(f'{{{WORD}}}abstractNumId') if instance is not None else None
            definition = next((item for item in root.findall(f'{{{WORD}}}abstractNum') if abstract is not None and item.get(f'{{{WORD}}}abstractNumId') == abstract.get(f'{{{WORD}}}val')), None)
            kind = definition.find(f'{{{WORD}}}lvl/{{{WORD}}}numFmt') if definition is not None else None
            result['style'] = 'bullet' if kind is not None and kind.get(f'{{{WORD}}}val') == 'bullet' else 'number'
    else:
        if node.tag == f'{{{TEXT}}}h':
            result['style'] = 'heading2' if node.get(f'{{{TEXT}}}outline-level') == '2' else 'heading1'
        parent = node.getparent()
        if parent is not None and parent.tag == f'{{{TEXT}}}list-item':
            result['style'] = 'number' if 'Number' in parent.getparent().get(f'{{{TEXT}}}style-name', '') else 'bullet'
        name = node.get(f'{{{TEXT}}}style-name')
        styles = document.tree.findall(f'.//{{{STYLE}}}style')
        if 'styles.xml' in document.archive.namelist():
            styles += part(document, 'styles.xml', f'{{{OFFICE}}}document-styles').findall(f'.//{{{STYLE}}}style')
        style = next((item for item in styles if item.get(f'{{{STYLE}}}name') == name), None)
        props = style.find(f'{{{STYLE}}}text-properties') if style is not None else None
        if props is not None:
            result['bold'] = props.get(f'{{{FO}}}font-weight') == 'bold'
            result['italic'] = props.get(f'{{{FO}}}font-style') == 'italic'
    return result


def append_paragraph(document):
    if len(document.paragraphs) >= 3000:
        raise HTTPException(413, 'The document contains too many paragraphs')
    parent = document.tree.find(f'{{{WORD}}}body') if document.word else document.tree.find(f'.//{{{OFFICE}}}text')
    if parent is None:
        raise HTTPException(415, 'The document has no editable body')
    node = etree.Element(f'{{{WORD}}}p' if document.word else f'{{{TEXT}}}p')
    section = parent.find(f'{{{WORD}}}sectPr') if document.word else None
    parent.insert(parent.index(section) if section is not None else len(parent), node)
    document.paragraphs.append(node)
    document.slots.append(document.text_slots(node))


def detach_odt_list(node):
    item = node.getparent()
    if item.tag != f'{{{TEXT}}}list-item':
        return
    listing = item.getparent()
    if len(item) != 1:
        raise HTTPException(422, 'Complex nested lists are preserved without reformatting')
    parent = listing.getparent()
    position = parent.index(listing)
    index = listing.index(item)
    after = copy.copy(listing)
    for child in list(after):
        after.remove(child)
    for child in list(listing)[index + 1:]:
        listing.remove(child)
        after.append(child)
    item.remove(node)
    listing.remove(item)
    parent.insert(position + 1, node)
    if len(after):
        parent.insert(position + 2, after)
    if not len(listing):
        parent.remove(listing)


def apply_format(document, node, change):
    current = format_info(document, node)
    values = {key: getattr(change, key, None) if getattr(change, key, None) is not None else current[key] for key in current}
    if values == current:
        return
    style = values['style']
    if document.word:
        props = property_node(node, f'{{{WORD}}}pPr')
        if style != current['style']:
            for name in ('pStyle', 'numPr', 'outlineLvl'):
                child = props.find(f'{{{WORD}}}{name}')
                if child is not None:
                    props.remove(child)
            if style.startswith('heading'):
                level = '1' if style == 'heading1' else '2'
                etree.SubElement(props, f'{{{WORD}}}pStyle', {f'{{{WORD}}}val': 'Heading' + level})
                etree.SubElement(props, f'{{{WORD}}}outlineLvl', {f'{{{WORD}}}val': str(int(level) - 1)})
            elif style in {'bullet', 'number'}:
                num = etree.SubElement(props, f'{{{WORD}}}numPr')
                etree.SubElement(num, f'{{{WORD}}}ilvl', {f'{{{WORD}}}val': '0'})
                etree.SubElement(num, f'{{{WORD}}}numId', {f'{{{WORD}}}val': word_number(document, style)})
        for run in node.iter(f'{{{WORD}}}r'):
            properties = property_node(run, f'{{{WORD}}}rPr')
            for key, name in [('bold', 'b'), ('italic', 'i')]:
                if values[key] != current[key]:
                    child = property_node(properties, f'{{{WORD}}}{name}')
                    child.set(f'{{{WORD}}}val', '1' if values[key] else '0')
            if style != current['style']:
                size = property_node(properties, f'{{{WORD}}}sz')
                size.set(f'{{{WORD}}}val', '36' if style == 'heading1' else '30' if style == 'heading2' else '22')
    else:
        if style != current['style']:
            detach_odt_list(node)
            node.tag = f'{{{TEXT}}}h' if style.startswith('heading') else f'{{{TEXT}}}p'
            node.attrib.pop(f'{{{TEXT}}}outline-level', None)
            if style.startswith('heading'):
                node.set(f'{{{TEXT}}}outline-level', '1' if style == 'heading1' else '2')
        automatic = document.tree.find(f'{{{OFFICE}}}automatic-styles')
        if automatic is None:
            automatic = etree.Element(f'{{{OFFICE}}}automatic-styles')
            document.tree.insert(0, automatic)
        identifiers = {element.get(f'{{{STYLE}}}name') for element in automatic}
        name = 'RootDriveParagraph' + str(len(identifiers) + 1)
        while name in identifiers:
            name += '1'
        attributes = {f'{{{STYLE}}}name': name, f'{{{STYLE}}}family': 'paragraph'}
        previous = node.get(f'{{{TEXT}}}style-name')
        if previous:
            attributes[f'{{{STYLE}}}parent-style-name'] = previous
        definition = etree.SubElement(automatic, f'{{{STYLE}}}style', attributes)
        properties = {f'{{{FO}}}font-weight': 'bold' if values['bold'] else 'normal', f'{{{FO}}}font-style': 'italic' if values['italic'] else 'normal'}
        if style.startswith('heading'):
            properties[f'{{{FO}}}font-size'] = '18pt' if style == 'heading1' else '15pt'
        etree.SubElement(definition, f'{{{STYLE}}}text-properties', properties)
        node.set(f'{{{TEXT}}}style-name', name)
        if style in {'bullet', 'number'} and style != current['style']:
            list_name = document.list_ids.get(style)
            if list_name is None:
                list_name = 'RootDrive' + ('Bullet' if style == 'bullet' else 'Number')
                while list_name in identifiers:
                    list_name += '1'
                definition = etree.SubElement(automatic, f'{{{TEXT}}}list-style', {f'{{{STYLE}}}name': list_name})
                attributes = {f'{{{TEXT}}}level': '1'}
                attributes[f'{{{TEXT}}}bullet-char' if style == 'bullet' else f'{{{STYLE}}}num-format'] = '•' if style == 'bullet' else '1'
                if style == 'number':
                    attributes[f'{{{STYLE}}}num-suffix'] = '.'
                etree.SubElement(definition, f'{{{TEXT}}}list-level-style-' + ('bullet' if style == 'bullet' else 'number'), attributes)
                document.list_ids[style] = list_name
            parent = node.getparent()
            previous = node.getprevious()
            if previous is not None and previous.tag == f'{{{TEXT}}}list' and previous.get(f'{{{TEXT}}}style-name') == list_name:
                listing = previous
            else:
                listing = etree.Element(f'{{{TEXT}}}list', {f'{{{TEXT}}}style-name': list_name})
                parent.insert(parent.index(node), listing)
            parent.remove(node)
            etree.SubElement(listing, f'{{{TEXT}}}list-item').append(node)
