import EncounterDetailClient from "./EncounterDetailClient";

export default async function EncounterPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EncounterDetailClient id={id} />;
}
