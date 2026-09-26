export default function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="p-5 flex flex-col gap-4 max-w-[1400px]">
      <header className="flex items-end justify-between gap-3 flex-wrap">
        <div><h1 className="px-title text-xl">{title}</h1>{subtitle && <p className="text-cream/70 text-[12px]">{subtitle}</p>}</div>
        {actions}
      </header>
      {children}
    </div>
  );
}
