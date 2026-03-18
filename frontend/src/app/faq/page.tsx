import { getTranslations } from "next-intl/server";
import Link from "next/link";

const FAQ_KEYS = Array.from({ length: 10 }, (_, i) => i + 1);

export default async function FaqPage() {
  const t = await getTranslations("faq");

  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ_KEYS.map((i) => ({
      "@type": "Question",
      name: t(`q${i}`),
      acceptedAnswer: { "@type": "Answer", text: t(`a${i}`) },
    })),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />
      <article className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
          {t("title")}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("intro")}</p>

        <div className="mt-8 space-y-6">
          {FAQ_KEYS.map((i) => (
            <details key={i} className="group border-b pb-4">
              <summary className="cursor-pointer font-medium text-sm sm:text-base select-none list-none flex items-start gap-2">
                <span className="text-muted-foreground mt-0.5 shrink-0 transition-transform group-open:rotate-90">
                  &#9654;
                </span>
                <span>{t(`q${i}`)}</span>
              </summary>
              <p className="mt-3 pl-5 text-sm text-muted-foreground leading-relaxed">
                {t(`a${i}`)}
              </p>
            </details>
          ))}
        </div>

        <hr className="my-8" />
        <p className="text-sm text-muted-foreground">
          <Link href="/" className="underline">
            {t("linkSimulator")}
          </Link>
          {" · "}
          <Link href="/methodology" className="underline">
            {t("linkMethodology")}
          </Link>
        </p>
      </article>
    </>
  );
}
