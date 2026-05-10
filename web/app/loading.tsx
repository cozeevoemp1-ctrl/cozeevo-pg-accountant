export default function HomeLoading() {
  return (
    <main className="flex flex-col gap-5 px-4 pt-6 pb-32 max-w-lg mx-auto">
      {/* Greeting */}
      <div className="flex flex-col gap-1.5">
        <div className="h-6 w-44 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="h-3.5 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
      </div>

      {/* Overview card */}
      <div className="bg-surface rounded-card border border-[#F0EDE9] p-5 flex flex-col gap-3">
        <div className="h-3.5 w-32 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="h-8 w-40 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="h-2 w-full bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="flex gap-4">
          <div className="h-3 w-20 bg-[#F0EDE9] rounded-full animate-pulse" />
          <div className="h-3 w-20 bg-[#F0EDE9] rounded-full animate-pulse" />
        </div>
      </div>

      {/* KPI tiles 2×2 */}
      <div className="grid grid-cols-2 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-surface rounded-card border border-[#F0EDE9] p-4 flex flex-col gap-2">
            <div className="h-3 w-16 bg-[#F0EDE9] rounded-full animate-pulse" />
            <div className="h-7 w-12 bg-[#F0EDE9] rounded-full animate-pulse" />
          </div>
        ))}
      </div>

      {/* Quick links row */}
      <div className="flex gap-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex-1 bg-surface border border-[#F0EDE9] rounded-card px-3 py-2.5 h-14 animate-pulse" />
        ))}
      </div>

      {/* Recent check-ins */}
      <div className="flex flex-col gap-2">
        <div className="h-3 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-1">
          {[1, 2, 3].map((i) => (
            <div key={i} className="py-3 border-b border-[#F0EDE9] last:border-0 flex justify-between items-center">
              <div className="flex flex-col gap-1.5">
                <div className="h-3.5 w-32 bg-[#F0EDE9] rounded-full animate-pulse" />
                <div className="h-2.5 w-20 bg-[#F0EDE9] rounded-full animate-pulse" />
              </div>
              <div className="h-6 w-14 bg-[#F0EDE9] rounded-pill animate-pulse" />
            </div>
          ))}
        </div>
      </div>

      {/* Recent payments */}
      <div className="flex flex-col gap-2">
        <div className="h-3 w-28 bg-[#F0EDE9] rounded-full animate-pulse" />
        <div className="bg-surface rounded-card border border-[#F0EDE9] px-4 py-1">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="py-3 border-b border-[#F0EDE9] last:border-0 flex justify-between items-center">
              <div className="flex flex-col gap-1.5">
                <div className="h-3.5 w-36 bg-[#F0EDE9] rounded-full animate-pulse" />
                <div className="h-2.5 w-24 bg-[#F0EDE9] rounded-full animate-pulse" />
              </div>
              <div className="h-4 w-16 bg-[#F0EDE9] rounded-full animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
