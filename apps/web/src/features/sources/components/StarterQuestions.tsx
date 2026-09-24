import { Sparkles } from 'lucide-react'

export function StarterQuestions({ questions }: { questions: string[] | null }) {
  if (!questions || questions.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 shadow-sm">
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Sparkles size={13} className="text-accent" aria-hidden="true" />
        Starter questions:
      </span>
      {questions.map((question) => (
        <span
          key={question}
          className="rounded-full border border-accent/20 bg-accent-soft px-2.5 py-1 text-xs text-foreground"
        >
          {question}
        </span>
      ))}
    </div>
  )
}
