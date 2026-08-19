import { Badge } from "@/components/ui/badge";
import { statusBadge, type StatusDomain } from "@/lib/status";

export function StatusBadge({ domain, value }: { domain: StatusDomain; value: string }) {
  const { variant, label } = statusBadge(domain, value);
  return <Badge variant={variant} className="capitalize">{label}</Badge>;
}
