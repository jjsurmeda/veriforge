import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function IconButton({ children, size = 32, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode; size?: 28 | 32 }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg text-fg-muted transition-[background-color,color,transform] duration-150 ease-out hover:bg-raised hover:text-fg active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-40 motion-reduce:transform-none motion-reduce:transition-none ${size === 28 ? 'size-7' : 'size-8'} ${className}`}
    >
      {children}
    </button>
  )
}
