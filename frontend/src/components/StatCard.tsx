interface Props {
  label: string;
  value: number | string;
  sub?: string;
  color?: string;
  accent?: string;
  icon?: React.ReactNode;
}

export default function StatCard({ label, value, sub, color = "text-white", accent, icon }: Props) {
  return (
    <div className={`bg-gray-900 border border-gray-800 rounded-xl p-5 ${accent ?? ""}`}>
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <p className="text-xs text-gray-500 uppercase tracking-widest">{label}</p>
      </div>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
    </div>
  );
}
