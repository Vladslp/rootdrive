const names = ["files", "trash", "versions", "temporary", "system", "free"];
export function StorageArtwork({ index }: { index: number }) {
  return <span className="storage-artwork" aria-hidden="true"
    style={{ backgroundImage: `url(/assets/icons/storage-${names[index]}.webp)`, backgroundSize: "100% 100%", backgroundPosition: "center" }} />;
}
