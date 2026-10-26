export function SurfaceAction({
  label,
  activate,
}: {
  label: string;
  activate: () => void;
}) {
  return (
    <button
      type="button"
      className="surface-action"
      aria-label={label}
      onClick={activate}
    />
  );
}
