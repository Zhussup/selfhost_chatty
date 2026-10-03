import { cycleTheme, useTheme } from "../theme";
import Icon, { type IconName } from "./Icon";

const ICON: Record<string, IconName> = { light: "sun", dark: "moon", system: "monitor" };
const LABEL: Record<string, string> = {
  light: "Light theme",
  dark: "Dark theme",
  system: "System theme",
};

export default function ThemeToggle() {
  const theme = useTheme();
  return (
    <button
      type="button"
      className="icon"
      title={`${LABEL[theme]} — click to switch`}
      aria-label={`${LABEL[theme]}, click to switch`}
      onClick={cycleTheme}
    >
      <Icon name={ICON[theme]} />
    </button>
  );
}
