import { getTranslations } from "next-intl/server";
import Link from "next/link";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-8">
      <h2 className="text-lg sm:text-xl font-semibold mb-3">{title}</h2>
      <div className="space-y-2 text-sm sm:text-base text-muted-foreground leading-relaxed">
        {children}
      </div>
    </section>
  );
}

export default async function MethodologyPage() {
  const t = await getTranslations("methodology");

  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
      <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
        {t("title")}
      </h1>
      <p className="mt-2 text-sm sm:text-base text-muted-foreground leading-relaxed">
        {t("intro")}
      </p>

      <Section title={t("bootstrapTitle")}>
        <p>{t("bootstrapP1")}</p>
        <p>{t("bootstrapP2")}</p>
        <p>{t("bootstrapP3")}</p>
      </Section>

      <Section title={t("mcTitle")}>
        <p>{t("mcP1")}</p>
        <p>{t("mcP2")}</p>
      </Section>

      <Section title={t("successTitle")}>
        <p>{t("successP1")}</p>
      </Section>

      <Section title={t("fundedTitle")}>
        <p>{t("fundedP1")}</p>
      </Section>

      <Section title={t("guardrailTitle")}>
        <p>{t("guardrailP1")}</p>
        <p>{t("guardrailP2")}</p>
        <p>{t("guardrailP3")}</p>
      </Section>

      <Section title={t("dataTitle")}>
        <p>{t("dataP1JST")}</p>
        <p>{t("dataP2Fire")}</p>
        <p>{t("dataP3")}</p>
        <h3 className="text-base font-medium text-foreground mt-4 mb-1">
          {t("countriesTitle")}
        </h3>
        <p>{t("countriesP1")}</p>
      </Section>

      <Section title={t("limitationsTitle")}>
        <p>{t("limitP1")}</p>
        <p>{t("limitP2")}</p>
        <p>{t("limitP3")}</p>
      </Section>

      <hr className="my-8 border-border" />
      <p className="text-sm text-muted-foreground">
        <Link href="/" className="underline">
          {t("linkSimulator")}
        </Link>
        {" · "}
        <Link href="/faq" className="underline">
          {t("linkFaq")}
        </Link>
      </p>
    </article>
  );
}
