export type SourceType = "ERP" | "BANK" | "GATEWAY";
export type TransactionStatus = "UNRECONCILED" | "MATCHED" | "DISCREPANCY" | "IGNORED";

export interface Batch {
  id: string;
  original_filename: string;
  source_type: SourceType;
  source_account: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
  total_records: number;
  processed_records: number;
  imported_records: number;
  duplicate_records: number;
  failed_records: number;
  progress_percentage: number;
  error_message: string;
  created_at: string;
}

export interface BatchProgress {
  id: string;
  state: Batch["status"];
  percentage: number;
  processed_records: number;
  total_records: number;
  imported_records: number;
  duplicate_records: number;
  failed_records: number;
  error: string | null;
}

export interface Transaction {
  id: string;
  reference: string;
  batch_id: string;
  source_type: SourceType;
  amount: string;
  currency: string;
  timestamp: string;
  counterparty: string;
  direction: "CREDIT" | "DEBIT";
  status: TransactionStatus;
  description: string;
}

export interface Discrepancy {
  id: string;
  discrepancy_type: string;
  status: "OPEN" | "IN_REVIEW" | "RESOLVED" | "IGNORED";
  primary_reference: string;
  primary_amount: string;
  secondary_reference: string | null;
  secondary_amount: string | null;
  expected_amount: string | null;
  actual_amount: string | null;
  variance_amount: string | null;
  details: { reason?: string; candidate_ids?: string[] };
  created_at: string;
  resolution_note: string;
}

export interface Summary {
  total_uploaded: number;
  matched: number;
  match_rate: number;
  pending_discrepancies: number;
  total_variance: string | null;
  variance_by_currency: Record<string, string>;
}

export interface PagedResponse<T> {
  data: T[];
  meta: { page: number; page_size: number; total: number; has_next: boolean; has_previous: boolean };
}

export interface CurrentUser {
  username: string;
  organization: string;
  role: "ADMIN" | "FINANCE_MANAGER" | "AUDITOR";
  read_only: boolean;
  public_demo: boolean;
}

export interface ReconciliationRun {
  id: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  ledger_batch_id: string;
  external_batch_id: string;
  matched_count: number;
  discrepancy_count: number;
  error_message: string;
}
