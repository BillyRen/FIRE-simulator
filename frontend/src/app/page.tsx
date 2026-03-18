import { PageHero } from "@/components/page-hero";
import { SimulatorClient } from "./simulator-client";

export default function Page() {
  return (
    <>
      <PageHero ns="simulator" />
      <SimulatorClient />
    </>
  );
}
