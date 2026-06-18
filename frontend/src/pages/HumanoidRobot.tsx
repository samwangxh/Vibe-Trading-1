import { useTranslation } from "react-i18next";

export function HumanoidRobot() {
  const { t } = useTranslation();
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <div className="text-center">
        <h2 className="text-2xl font-semibold tracking-tight">{t('humanoidRobot.title')}</h2>
        <p className="mt-2 text-sm">{t('humanoidRobot.placeholder')}</p>
      </div>
    </div>
  );
}