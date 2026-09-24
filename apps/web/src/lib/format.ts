const creditFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

export function formatCredits(value: number): string {
  return creditFormatter.format(value)
}
