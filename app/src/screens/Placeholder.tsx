type Props = { title: string };

export function Placeholder({ title }: Props) {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">{title}</h1>
      <p className="text-gray-400 text-sm">This screen is not yet implemented.</p>
    </div>
  );
}
