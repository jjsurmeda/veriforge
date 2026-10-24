import data from './benchmarks.json'

/** Stored benchmark numbers, bundled from `docs/benchmarks/`. Static on
 *  purpose: no live comparison and no model calls. Each table names the run
 *  it came from. */
function usd(value: number): string {
  return `$${value.toFixed(value < 0.1 ? 3 : 2)}`
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-border text-2xs uppercase tracking-[0.08em] text-fg-muted">
            {head.map((h) => (
              <th key={h} scope="col" className="px-2 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70 font-mono tabular-nums text-fg">{children}</tbody>
      </table>
    </div>
  )
}

export function BenchmarksPanel() {
  const { rerankers, decision_layer: dl } = data
  return (
    <div className="space-y-4">
      <section className="overflow-hidden rounded-xl border border-border bg-surface">
        <h2 className="border-b border-border bg-sidebar px-4 py-3 text-xs font-semibold text-fg">{rerankers.title}</h2>
        <div className="space-y-3 p-4">
          <p className="text-xs leading-5 text-fg-muted">{rerankers.run}</p>
          <Table head={['Reranker', 'recall@8', 'nDCG@10', 'p50', 'p95', '$ / 1k queries', 'Cost source']}>
            {rerankers.rows.map((r) => (
              <tr key={r.id}>
                <th scope="row" className="px-2 py-2 font-medium">{r.id}</th>
                <td className="px-2 py-2">{r.hits}/{r.items} ({r.recall_at_8.toFixed(3)})</td>
                <td className="px-2 py-2">{r.ndcg_at_10.toFixed(4)}</td>
                <td className="px-2 py-2">{r.p50_ms} ms</td>
                <td className="px-2 py-2">{r.p95_ms} ms</td>
                <td className="px-2 py-2">{usd(r.cost_per_1k_queries_usd)}</td>
                <td className="px-2 py-2 font-sans text-fg-muted">{r.cost_source}</td>
              </tr>
            ))}
          </Table>
          <p className="text-2xs text-fg-muted">Source: {rerankers.source}</p>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-surface">
        <h2 className="border-b border-border bg-sidebar px-4 py-3 text-xs font-semibold text-fg">{dl.title}</h2>
        <div className="space-y-3 p-4">
          <p className="text-xs leading-5 text-fg-muted">{dl.run}</p>
          <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-fg-muted">
            {dl.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
          <Table head={['Area', 'Jev p50', 'Judge p50 (in-flight)', 'Speed', 'Jev $ / 1k', 'Judge $ / 1k', 'Cost', 'Agreement']}>
            {dl.rows.map((r) => (
              <tr key={r.area}>
                <th scope="row" className="px-2 py-2 font-sans font-medium">{r.area}</th>
                <td className="px-2 py-2">{r.jev_p50_ms.toLocaleString('en-US')} ms</td>
                <td className="px-2 py-2">{r.judge_p50_ms.toLocaleString('en-US')} ms</td>
                <td className="px-2 py-2">{r.speed_ratio}</td>
                <td className="px-2 py-2">{usd(r.jev_usd_per_1k)}</td>
                <td className="px-2 py-2">{usd(r.judge_usd_per_1k)}</td>
                <td className="px-2 py-2">{r.cost_ratio}</td>
                <td className="px-2 py-2">{r.agreement}</td>
              </tr>
            ))}
          </Table>
          <p className="text-2xs text-fg-muted">Source: {dl.source}</p>
        </div>
      </section>
    </div>
  )
}
