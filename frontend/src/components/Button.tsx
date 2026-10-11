import type { ComponentPropsWithoutRef } from 'react'

type ButtonProps = ComponentPropsWithoutRef<'button'> & {
  variant?: 'primary' | 'secondary'
}

const variants = {
  primary: 'border-ink bg-ink text-white enabled:hover:bg-ink-soft',
  secondary: 'border-line bg-white text-ink enabled:hover:bg-paper',
} satisfies Record<NonNullable<ButtonProps['variant']>, string>

export function Button({ variant = 'primary', type = 'button', className = '', children, ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-11 items-center justify-center rounded-lg border px-4 py-2 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
