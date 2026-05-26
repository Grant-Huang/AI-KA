import type { SSEEvent } from './protocol';
/**
 * Returns true if the event's schema_version is compatible with this runtime.
 * Compatible means major version matches (minor additions are allowed).
 */
export declare function isCompatibleVersion(ev: SSEEvent): boolean;
/**
 * Throws if the event's schema_version is incompatible with this runtime.
 * Use at the transport boundary when you want hard guarantees.
 */
export declare function assertCompatibleVersion(ev: SSEEvent): void;
