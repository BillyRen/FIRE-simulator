import { getTranslations } from "next-intl/server";

interface PageHeroProps {
  ns: string;
}

export async function PageHero({ ns }: PageHeroProps) {
  const t = await getTranslations(`seo.${ns}`);

  return (
    <section className="max-w-[1600px] mx-auto px-3 sm:px-6 pt-4 sm:pt-6 pb-0">
      <h1 className="text-xl sm:text-2xl font-bold tracking-tight">
        {t("h1")}
      </h1>
      <p className="mt-1.5 text-sm text-muted-foreground max-w-3xl leading-relaxed">
        {t("intro")}
      </p>
    </section>
  );
}
