"use client";

interface StarRatingProps {
  label: string;
  description: string;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

/** 1-5 star input. 0 means "not rated yet". */
export default function StarRating({
  label,
  description,
  value,
  onChange,
  disabled = false,
}: StarRatingProps) {
  return (
    <div>
      <p className="text-sm font-medium text-gray-900">{label}</p>
      <p className="text-xs text-gray-500">{description}</p>
      <div className="mt-1 flex gap-1" role="radiogroup" aria-label={label}>
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            role="radio"
            aria-checked={value === star}
            aria-label={`${star} star${star !== 1 ? "s" : ""}`}
            disabled={disabled}
            onClick={() => onChange(star)}
            className={`text-2xl leading-none transition-colors disabled:cursor-not-allowed ${
              star <= value ? "text-cda-gold" : "text-gray-300 hover:text-cda-gold/60"
            }`}
          >
            ★
          </button>
        ))}
      </div>
    </div>
  );
}
