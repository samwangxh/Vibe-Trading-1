import { useTranslation } from "react-i18next";

export function Overview() {
  const { t } = useTranslation();
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <div className="text-center">
        <h2 className="text-2xl font-semibold tracking-tight">{t('overview.title')}</h2>
        <p className="mt-2 text-sm">{t('overview.placeholder')}</p>
      </div>
    </div>
  );
}