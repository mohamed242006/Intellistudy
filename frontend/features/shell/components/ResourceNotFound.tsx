import { ButtonLink } from "@/design-system/components/Button";
import { EmptyState } from "@/design-system/components/EmptyState";

/**
 * The single not-found state for documents, summaries and conversations (gate GF1-17). Missing, foreign and malformed
 * ids reach it through the same backend 404; it names nothing about the requested resource.
 */
export function ResourceNotFound() {
  return (
    <div className="px-4 py-10 lg:px-12">
      <EmptyState
        size="page"
        icon="search"
        headingLevel={1}
        title="Not found"
        body="This page doesn’t exist or isn’t available to your account."
        action={<ButtonLink href="/">Back to Dashboard</ButtonLink>}
      />
    </div>
  );
}
