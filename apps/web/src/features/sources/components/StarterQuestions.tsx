export function StarterQuestions({ questions }: { questions: string[] | null }) {
  if (!questions || questions.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-paper/40">Starter questions:</span>
      {questions.map((question) => (
        <span
          key={question}
          className="rounded border border-mist bg-graphite px-2.5 py-1 text-xs text-paper/80"
        >
          {question}
        </span>
      ))}
    </div>
  )
}
