import type { NavIconName } from "../app/platform";

function NavIcon({ name }: { name: NavIconName }) {
  const commonProps = {
    className: "nav-icon",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
  };

  switch (name) {
    case "overview":
      return <svg {...commonProps}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>;
    case "documents":
      return <svg {...commonProps}><path d="M6 3.5h8l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" /><path d="M14 3.5V8h4M8 12h6M8 16h8" /></svg>;
    case "operations":
      return <svg {...commonProps}><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="M7 6h10M6.5 7.5l4.3 8.7M17.5 7.5l-4.3 8.7" /></svg>;
    case "requirements":
      return <svg {...commonProps}><path d="m4 6 1.5 1.5L8.5 4.5M11 6h9M4 12l1.5 1.5 3-3M11 12h9M4 18l1.5 1.5 3-3M11 18h9" /></svg>;
    case "cases":
      return <svg {...commonProps}><path d="M9 5h6M9 3h6v4H9z" /><path d="M7 5H5.5A1.5 1.5 0 0 0 4 6.5v13A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-13A1.5 1.5 0 0 0 18.5 5H17" /><path d="m8 14 2.5 2.5L16 11" /></svg>;
    case "execution":
      return <svg {...commonProps}><circle cx="12" cy="12" r="9" /><path d="m10 8 6 4-6 4Z" /></svg>;
    case "reports":
      return <svg {...commonProps}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>;
    case "settings":
      return <svg {...commonProps}><path d="M4 6h8M16 6h4M4 12h3M11 12h9M4 18h10M18 18h2" /><circle cx="14" cy="6" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="16" cy="18" r="2" /></svg>;
  }
}

function BrandMark() {
  return <svg className="brand-symbol" viewBox="0 0 40 40" fill="none" aria-hidden="true" focusable="false"><circle cx="10" cy="12" r="3" /><circle cx="30" cy="10" r="3" /><circle cx="29" cy="29" r="3" /><path d="M13 12h7c5 0 7-2 7-2M12 15l13 11M29 13v13" /></svg>;
}


export { NavIcon, BrandMark };

