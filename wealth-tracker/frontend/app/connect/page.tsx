"use client";
import AgentConsent from "@trackerai/ui/account/AgentConsent";
import AccountGate from "@/components/AccountGate";
import { api } from "@/lib/api";

export default function ConnectPage() {
  return <AgentConsent api={api} setup={(account, done) => <AccountGate me={account} onReady={done} />} />;
}
