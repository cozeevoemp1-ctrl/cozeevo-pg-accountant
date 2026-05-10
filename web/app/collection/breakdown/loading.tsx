export default function CollectionLoading() {
  return (
    <main className="flex flex-col gap-4 px-4 pt-6 pb-24 max-w-lg mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-[#F0EDE9] animate-pulse" />
        <div className="h-5 w-40 bg-[#F0EDE9] rounded-full animate-pulse" />
      </div>

      {/* Month picker */}
      <div className="flex items-center justify-between bg-surface rounded-card border border-[#F0EDE9] px-4 py-3">
        <div className="w-8 h-8 rounded-full bg-[#F0EDE9] animate-pulse" />
        <div className="h-4 w-32 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="w-8 h-8 rounded-full bg-[#F0EDE9] animate-pulse" />
      </div>

      {/* Summary stats */}
      <div className="bg-surface rounded-card border border-[#F0EDE9] p-5 flex flex-col gap-3">
        <div className="h-3 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="h-9 w-36 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="h-2.5 w-full bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="flex gap-4 pt-1">
          <div className="h-3 w-24 bg-[#F0EDE9] rounded-full animate-pulse" />
          <div className="h-3 w-24 bg-[#F0EDE9] rounded-full animate-pulse" />
        </div>
      </div>

      {/* Payment method breakdown */}
      <div className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-3">
        <div className="h-3 w-32 bg-[#F0EDE9] rounded-full animate-pulse mb-1" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex justify-between items-center">
            <div className="h-3.5 w-20 bg-[#F0EDE9] rounded-full animate-pulse" />
            <div className="h-3.5 w-24 bg-[#F0EDE9] rounded-full animate-pulse" />
          </div>
        ))}
      </div>

      {/* Tenant list */}
      <div className="flex flex-col gap-2">
        <div className="h-3 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex justify-between items-center">
            <div className="flex flex-col gap-1.5">
              <div className="h-3.5 w-32 bg-[#F0EDE9] rounded-full animate-pulse" />
              <div className="h-2.5 w-20 bg-[#F0EDE9] rounded-full animate-pulse" />
            </div>
            <div className="h-6 w-16 bg-[#F0EDE9] rounded-pill animate-pulse" />
          </div>
        ))}
      </div>
    </main>
  );
}
