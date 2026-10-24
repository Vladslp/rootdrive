# RootDrive visual assets

## Storage icon pack

`storage-icons.png` is one 1536 × 1024 transparent atlas, generated with the built-in ImageGen tool on October 25, 2026. Row-major order: RootDrive files, Trash, Versions, Temporary, System, Free. The generated alpha is preserved; no OS background removal or post-processing was applied. CSS uses six equal square cells, a 300% × 200% background size and matching background positions. Separate early candidates were discarded and are not shipped.

Final prompt:

> Use case: stylized-concept. Create ONE cohesive UI ICON PACK as a precise 3-column by 2-row sprite atlas, landscape 1536x1024, with 6 equally sized square cells and genuinely transparent background everywhere outside the icon objects. Each icon centered at exactly the center of its own cell, occupying 65-70% of the cell. All six share identical optical size, rounded soft clay illustration style, minimal 2.5D bevel, gentle satin pastel shading and consistent slight front three-quarter view. No photorealism, no metal, no realistic glass, no glow, no shadows outside the objects, no grid lines, no background tiles, no labels, no typography. Opaque ivory highlights; do not make internal white elements transparent. Fits RootDrive's blue/lavender/yellow/mint illustrated folder icons and clean white or dark navy dashboard. EXACT order: TOP LEFT cornflower-blue storage drive with pale ivory front and two simple blue file sheets behind, representing personal files; TOP CENTER dusty-rose rounded trash bin with lid and tiny ivory inset details; TOP RIGHT lavender stacked document sheets with a bold ivory history arrow and tiny clock; BOTTOM LEFT honey-yellow simple rounded hourglass with ivory center and golden sand, representing temporary data; BOTTOM CENTER slate-blue rounded microchip with short thick pins and a pale ivory gear at its center, representing system; BOTTOM RIGHT mint-green bold chunky rounded checkmark, representing free space, no tile or circle. Clear polished silhouettes legible at 48px, generous empty transparent margins in every cell, balanced coherent set.

Created for this project using the built-in ImageGen tool. Initial background removal used Finder → Quick Actions → Remove Background on macOS. The application icon, folder atlas and main file atlas were then refined with ImageGen to preserve solid interior highlights that macOS had removed. Original generations are preserved outside the repository.

- `app-icon.png`: a minimal flat 2D charcoal mark showing three HDD glyphs joined by a branching root, with blue status dashes. The exterior is generated transparency; no macOS background removal was applied to this replacement.
- `folders.png`: 3 × 2 atlas, blue / lavender / yellow folders, mint folder / upload cloud / storage drive.
- `files.png`: 3 × 2 atlas, photos / video / audio, documents / archive / PDF.
- `extra.png`: 2 × 2 atlas, spreadsheet / presentation, code / generic document.

Atlases are displayed using CSS background positioning; no runtime image processing or external image service is needed. Action buttons use Lucide symbols for clarity and accessibility.

Generation prompts used soft matte 3D clay objects, generous margins, restrained pastel colors, consistent studio lighting and no text. The application icon brief joined a white storage drive with three branching roots on a rounded blue square. The first two atlases requested exact 3-column, 2-row grids. The additional file atlas requested a 2-column, 2-row grid with a transparent background.

The replacement application mark was generated with the built-in ImageGen tool on October 24, 2026. Final prompt: “Create a single minimalist flat 2D RootDrive graphic: three charcoal rounded rectangular HDD glyphs, simple circular disk marks and tiny blue status dashes, connected by short thick smooth root branches meeting below. Front-facing, geometric, generous negative space, readable at 24 pixels. Maximum two flat colors, charcoal and blue. Transparent exterior. No folder, cloud, text, perspective, realism, 3D, texture, gradients or shadows.” The original realistic candidate was rejected and is not shipped. Dark theme displays the final image as a light monochrome silhouette with CSS; the PNG alpha is preserved.
