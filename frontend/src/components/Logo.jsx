export default function Logo({ size = 40 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Outer circle - representing voice/speech */}
        <circle cx="32" cy="32" r="28" stroke="#c084fc" strokeWidth="3" />
        
        {/* Inner sound wave pattern */}
        <path
          d="M20 32 C20 28, 24 24, 28 28 L28 36 C24 40, 20 36, 20 32"
          fill="#c084fc"
          opacity="0.6"
        />
        <path
          d="M28 32 C28 26, 32 22, 36 26 L36 38 C32 42, 28 38, 28 32"
          fill="#c084fc"
          opacity="0.8"
        />
        <path
          d="M36 32 C36 24, 40 20, 44 24 L44 40 C40 44, 36 40, 36 32"
          fill="#c084fc"
        />
        
        {/* AI brain node at center */}
        <circle cx="32" cy="32" r="4" fill="#fff" />
        <circle cx="32" cy="32" r="2" fill="#c084fc" />
      </svg>
      
      <span style={{ fontSize: '24px', fontWeight: '600', color: '#c084fc' }}>
        TalimBot
      </span>
    </div>
  );
}
