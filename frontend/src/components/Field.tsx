/**
 * Field.tsx — 输入 / 文本域 / 下拉，含失焦校验
 *
 * 反馈规范（BRIEF 第 4 节 #8）：
 * 错误文案用 grid-template-rows: 0fr → 1fr 展开，150ms，不跳版。
 */

import { useId, useState } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import "./Field.css";

interface FieldShellProps {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  htmlFor: string;
  children: ReactNode;
}

function FieldShell({
  label,
  hint,
  error,
  required,
  htmlFor,
  children,
}: FieldShellProps) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="field__required" aria-hidden="true">
            必填
          </span>
        ) : null}
      </label>
      {children}
      {/* 错误优先，否则显示 hint；用 grid 展开不跳版 */}
      <div
        className={`field__foot${error ? " is-error" : ""}`}
        data-open={error ? "1" : "0"}
      >
        <div className="field__foot-inner">
          {error ? (
            <span role="alert">{error}</span>
          ) : hint ? (
            <span className="field__hint">{hint}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ---------------- Input ---------------- */

export interface InputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  label: string;
  hint?: string;
  /** 失焦校验：返回错误文案或 null */
  validate?: (value: string) => string | null;
  onChange?: (value: string) => void;
  error?: string | null;
}

export function Input({
  label,
  hint,
  validate,
  onChange,
  error: externalError,
  required,
  onBlur,
  ...rest
}: InputProps) {
  const id = useId();
  const [touched, setTouched] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const error = externalError ?? (touched ? localError : null);

  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    setTouched(true);
    if (validate) setLocalError(validate(e.target.value));
    onBlur?.(e);
  };

  return (
    <FieldShell
      label={label}
      hint={hint}
      error={error}
      required={required}
      htmlFor={id}
    >
      <input
        {...rest}
        id={id}
        className={`field__input${error ? " is-error" : ""}`}
        aria-invalid={error ? true : undefined}
        onBlur={handleBlur}
        onChange={(e) => {
          onChange?.(e.target.value);
          // 已报错时边输入边重新校验，及时消除错误
          if (touched && validate) setLocalError(validate(e.target.value));
        }}
      />
    </FieldShell>
  );
}

/* ---------------- Textarea ---------------- */

export interface TextareaProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "onChange"> {
  label: string;
  hint?: string;
  onChange?: (value: string) => void;
}

export function Textarea({
  label,
  hint,
  onChange,
  required,
  ...rest
}: TextareaProps) {
  const id = useId();
  return (
    <FieldShell label={label} hint={hint} error={null} required={required} htmlFor={id}>
      <textarea
        {...rest}
        id={id}
        className="field__input field__textarea"
        onChange={(e) => onChange?.(e.target.value)}
      />
    </FieldShell>
  );
}

/* ---------------- Select ---------------- */

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange"> {
  label: string;
  hint?: string;
  options: Array<{ value: string; label: string }>;
  onChange?: (value: string) => void;
}

export function Select({
  label,
  hint,
  options,
  onChange,
  required,
  ...rest
}: SelectProps) {
  const id = useId();
  return (
    <FieldShell label={label} hint={hint} error={null} required={required} htmlFor={id}>
      <select
        {...rest}
        id={id}
        className="field__input field__select"
        onChange={(e) => onChange?.(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}
