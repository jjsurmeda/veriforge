import { CornerDownRight, Sparkles } from 'lucide-react'

export function StarterQuestions({ questions, onSelect }: { questions: string[] | null; onSelect?: (question: string) => void }) {
  if (!questions || questions.length === 0) return null
  return (
    <div className="rounded-xl border border-border bg-surface p-2">
      <div className="mb-1 flex items-center gap-1.5 px-2 py-1 text-xs font-medium text-muted-foreground"><Sparkles size={13} strokeWidth={1.75} className="text-accent" aria-hidden="true" /> Starter questions:</div>
      <div className="flex flex-wrap gap-1.5">
        {questions.map((question) => onSelect ? <button key={question} type="button" onClick={() => onSelect(question)} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-left text-xs text-foreground transition-colors duration-150 hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-accent"><CornerDownRight size={13} strokeWidth={1.75} className="text-muted-foreground" aria-hidden="true" />{question}</button> : <span key={question} className="inline-flex items-center rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-xs text-foreground">{question}</span>)}
      </div>
    </div>
  )
}
