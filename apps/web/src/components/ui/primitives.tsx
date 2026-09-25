import * as React from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { DropdownMenu, HoverCard, Popover, Select, Tooltip } from 'radix-ui'

const overlayClass =
  'z-50 rounded-xl border border-border-strong bg-popover p-1 text-fg shadow-popover outline-none data-[state=closed]:duration-100 data-[state=open]:duration-150'
const itemClass =
  'flex min-h-8 cursor-default select-none items-center gap-2 rounded-lg px-2.5 text-sm text-fg outline-none transition-colors duration-150 data-[highlighted]:bg-raised data-[highlighted]:text-fg data-[disabled]:pointer-events-none data-[disabled]:opacity-50'

type PopoverContentProps = React.ComponentPropsWithoutRef<typeof Popover.Content>
type MenuContentProps = React.ComponentPropsWithoutRef<typeof DropdownMenu.Content>
type MenuRadioItemProps = React.ComponentPropsWithoutRef<typeof DropdownMenu.RadioItem>
type SelectContentProps = React.ComponentPropsWithoutRef<typeof Select.Content>
type SelectItemProps = React.ComponentPropsWithoutRef<typeof Select.Item>
type HoverCardContentProps = React.ComponentPropsWithoutRef<typeof HoverCard.Content>
type TooltipContentProps = React.ComponentPropsWithoutRef<typeof Tooltip.Content>

export const PopoverRoot = Popover.Root
export const PopoverTrigger = Popover.Trigger
export const PopoverAnchor = Popover.Anchor
export const PopoverClose = Popover.Close

export function PopoverContent({ className = '', ...props }: PopoverContentProps) {
  return (
    <Popover.Portal>
      <Popover.Content {...props} className={`${overlayClass} ${className}`} />
    </Popover.Portal>
  )
}

export const Menu = DropdownMenu.Root
export const MenuTrigger = DropdownMenu.Trigger
export const MenuGroup = DropdownMenu.Group
export const MenuLabel = DropdownMenu.Label
export const MenuSeparator = DropdownMenu.Separator
export const MenuRadioGroup = DropdownMenu.RadioGroup
export const MenuRadioItem = DropdownMenu.RadioItem
export const MenuItem = DropdownMenu.Item
export const MenuItemIndicator = DropdownMenu.ItemIndicator

export function MenuContent({ className = '', ...props }: MenuContentProps) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content {...props} className={`${overlayClass} min-w-40 ${className}`} />
    </DropdownMenu.Portal>
  )
}

export function MenuRadioItemWithCheck({ children, className = '', ...props }: MenuRadioItemProps) {
  return (
    <DropdownMenu.RadioItem {...props} className={`${itemClass} relative pl-8 ${className}`}>
      <span className="absolute left-2">
        <DropdownMenu.ItemIndicator>
          <Check size={14} strokeWidth={1.75} aria-hidden="true" />
        </DropdownMenu.ItemIndicator>
      </span>
      {children}
    </DropdownMenu.RadioItem>
  )
}

export function MenuItemWithIcon({ children, className = '', ...props }: React.ComponentPropsWithoutRef<typeof DropdownMenu.Item>) {
  return <DropdownMenu.Item {...props} className={`${itemClass} ${className}`}>{children}</DropdownMenu.Item>
}

export const SelectRoot = Select.Root
export const SelectValue = Select.Value
export const SelectTrigger = Select.Trigger
export const SelectIcon = Select.Icon
export const SelectGroup = Select.Group
export const SelectLabel = Select.Label
export const SelectViewport = Select.Viewport
export const SelectItemText = Select.ItemText
export const SelectItemIndicator = Select.ItemIndicator

export function SelectContent({ className = '', children, position = 'popper', ...props }: SelectContentProps) {
  return (
    <Select.Portal>
      <Select.Content {...props} position={position} className={`${overlayClass} min-w-[var(--radix-select-trigger-width)] ${className}`}>
        {children}
      </Select.Content>
    </Select.Portal>
  )
}

export function SelectItem({ children, className = '', ...props }: SelectItemProps) {
  return (
    <Select.Item {...props} className={`${itemClass} relative pl-8 ${className}`}>
      <span className="absolute left-2">
        <Select.ItemIndicator>
          <Check size={14} strokeWidth={1.75} aria-hidden="true" />
        </Select.ItemIndicator>
      </span>
      <Select.ItemText>{children}</Select.ItemText>
    </Select.Item>
  )
}

export const SelectChevron = ChevronDown

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
