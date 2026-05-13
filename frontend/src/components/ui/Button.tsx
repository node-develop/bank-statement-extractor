import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger-ghost";
type Size = "sm" | "lg";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  children?: ReactNode;
}

export function Button({
  variant = "primary",
  size,
  leftIcon,
  rightIcon,
  children,
  className,
  ...rest
}: Props) {
  const cls = ["btn", `btn-${variant}`, size && `btn-${size}`, className].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} {...rest}>
      {leftIcon ? <span className="ic">{leftIcon}</span> : null}
      {children !== undefined && <span>{children}</span>}
      {rightIcon ? <span className="ic">{rightIcon}</span> : null}
    </button>
  );
}
