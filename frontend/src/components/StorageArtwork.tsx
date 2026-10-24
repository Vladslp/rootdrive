export function StorageArtwork({ index }: { index: number }) {
  return (
    <span
      className="storage-artwork"
      aria-hidden="true"
      style={{
        backgroundPosition: `${(index % 3) * 50}% ${Math.floor(index / 3) * 100}%`,
      }}
    />
  );
}
