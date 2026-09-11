import PatientExplanationClient from "./PatientExplanationClient";

export default async function PatientPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <PatientExplanationClient token={token} />;
}
