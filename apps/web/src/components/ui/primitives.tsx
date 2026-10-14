import * as React from 'react'
import { DropdownMenu, HoverCard, Popover, Tooltip } from 'radix-ui'

const overlayClass =
  'z-50 rounded-xl border border-border-strong bg-popover p-1 text-fg shadow-popover outline-none data-[state=closed]:duration-100 data-[state=open]:duration-150'
const itemClass =
  'flex min-h-8 cursor-default select-none items-center gap-2 rounded-lg px-2.5 text-sm text-fg outline-none transition-colors duration-150 data-[highlighted]:bg-raised data-[highlighted]:text-fg data-[disabled]:pointer-events-none data-[disabled]:opacity-50'

type PopoverContentProps = React.ComponentPropsWithoutRef<typeof Popover.Content>
type MenuContentProps = React.ComponentPropsWithoutRef<typeof DropdownMenu.Content>
type HoverCardContentProps = React.ComponentPropsWithoutRef<typeof HoverCard.Content>
type TooltipContentProps = React.ComponentPropsWithoutRef<typeof Tooltip.Content>

export const PopoverRoot = Popover.Root
export const PopoverTrigger = Popover.Trigger

export function PopoverContent({ className = '', ...props }: PopoverContentProps) {
  return (
    <Popover.Portal>
      <Popover.Content {...props} className={`${overlayClass} ${className}`} />
    </Popover.Portal>
  )
}

export const Menu = DropdownMenu.Root
export const MenuTrigger = DropdownMenu.Trigger

export function MenuContent({ className = '', ...props }: MenuContentProps) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content {...props} className={`${overlayClass} min-w-40 ${className}`} />
    </DropdownMenu.Portal>
  )
}

export function MenuItemWithIcon({ children, className = '', ...props }: React.ComponentPropsWithoutRef<typeof DropdownMenu.Item>) {
  return <DropdownMenu.Item {...props} className={`${itemClass} ${className}`}>{children}</DropdownMenu.Item>
}

export const HoverCardRoot = HoverCard.Root
export const HoverCardTrigger = HoverCard.Trigger

export function HoverCardContent({ className = '', ...props }: HoverCardContentProps) {
  return (
    <HoverCard.Portal>
      <HoverCard.Content {...props} role="tooltip" className={`${overlayClass} w-80 p-3 ${className}`} />
    </HoverCard.Portal>
  )
}

export const TooltipProvider = Tooltip.Provider
export const TooltipRoot = Tooltip.Root
export const TooltipTrigger = Tooltip.Trigger

export function TooltipContent({ className = '', sideOffset = 6, ...props }: TooltipContentProps) {
  return (
    <Tooltip.Portal>
      <Tooltip.Content {...props} sideOffset={sideOffset} className={`${overlayClass} px-2.5 py-1.5 text-xs ${className}`} />
    </Tooltip.Portal>
  )
}
