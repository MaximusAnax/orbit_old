import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

type Tone = "primary" | "secondary" | "ghost" | "danger";

const toneClasses: Record<Tone, string> = {
  primary: "border-[var(--accent)] bg-[var(--accent)] text-white hover:bg-[var(--accent-strong)]",
  secondary: "border-[var(--line)] bg-[var(--surface-raised)] text-[var(--foreground)] hover:border-[var(--line-strong)]",
  ghost: "border-transparent bg-transparent text-[var(--muted-strong)] hover:bg-[var(--surface-muted)] hover:text-[var(--foreground)]",
  danger: "border-[rgba(162,61,50,0.28)] bg-[rgba(162,61,50,0.08)] text-[var(--danger)] hover:bg-[rgba(162,61,50,0.12)]",
};

export function Button({
  children,
  tone = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: Tone;
}) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--radius)] border px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClasses[tone]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function LinkButton({
  children,
  href,
  tone = "secondary",
  className = "",
}: {
  children: ReactNode;
  href: ComponentProps<typeof Link>["href"];
  tone?: Tone;
  className?: string;
}) {
  return (
    <Link
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--radius)] border px-4 py-2 text-sm font-semibold transition ${toneClasses[tone]} ${className}`}
      href={href}
    >
      {children}
    </Link>
  );
}

export function IconBox({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] text-xs font-bold text-[var(--accent)] [&_svg]:size-4">
      {children}
    </span>
  );
}

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`surface ${className}`}>{children}</section>;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
}) {
  const tones = {
    neutral: "border-[var(--line)] bg-[var(--surface-raised)] text-[var(--muted-strong)]",
    accent: "border-transparent bg-[var(--accent-soft)] text-[var(--accent)]",
    success: "border-transparent bg-[rgba(36,112,74,0.12)] text-[var(--success)]",
    warning: "border-transparent bg-[rgba(154,103,29,0.12)] text-[var(--warning)]",
    danger: "border-transparent bg-[rgba(162,61,50,0.12)] text-[var(--danger)]",
  };

  return (
    <span className={`inline-flex items-center rounded-[var(--radius)] border px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function TextInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] px-3.5 py-3 text-sm text-[var(--foreground)] transition placeholder:text-[var(--muted)] focus:border-[var(--accent)] ${className}`}
      {...props}
    />
  );
}

export function TextArea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full rounded-[var(--radius)] border border-[var(--line)] bg-[var(--surface-raised)] px-4 py-3 text-sm leading-6 text-[var(--foreground)] transition placeholder:text-[var(--muted)] focus:border-[var(--accent)] ${className}`}
      {...props}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-[var(--radius)] border border-dashed border-[var(--line-strong)] bg-[var(--surface-raised)] px-5 py-8 text-center">
      <p className="font-semibold text-[var(--foreground)]">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
