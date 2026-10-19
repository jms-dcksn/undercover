import { label, money } from "./format";
import type { JsonValue, RecordData } from "./types";

function Value({ value }: Readonly<{ value: JsonValue }>) {
  if (value === null) return <span>None</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ul className="record-list">
        {value.map((item, index) => (
          <li key={JSON.stringify([index, item])}>
            <Value value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span>None</span>
    );
  return <RecordFields data={value} />;
}

export function RecordFields({ data }: Readonly<{ data: RecordData }>) {
  return (
    <dl className="record-fields">
      {Object.entries(data).map(([key, value]) => (
        <div key={key}>
          <dt>{label(key)}</dt>
          <dd>
            {typeof value === "number" &&
            /^(amount($|_)|trip_cost$|deductible$)|_(max|limit)$/.test(key) ? (
              money(value)
            ) : (
              <Value value={value} />
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ClaimRecords({
  claim,
}: Readonly<{
  claim: {
    story: string;
    items: { description: string; category: string; amount: number }[];
    documents: { name: string; type: string; content: string }[];
  };
}>) {
  return (
    <>
      <section className="panel content-panel">
        <div className="section-heading">
          <span className="eyebrow">THE CUSTOMER'S ACCOUNT</span>
          <h2>What happened</h2>
        </div>
        <p className="story">{claim.story}</p>
        <h3>Items claimed</h3>
        <div className="items">
          {claim.items.map((item) => (
            <div
              className="expense"
              key={`${item.description}-${item.category}`}
            >
              <span>
                {item.description}
                <small>{label(item.category)}</small>
              </span>
              <strong className="amount">{money(item.amount)}</strong>
            </div>
          ))}
        </div>
      </section>
      <section className="panel content-panel">
        <div className="section-heading">
          <span className="eyebrow">SUPPORTING EVIDENCE</span>
          <h2>
            Documents <span className="muted">({claim.documents.length})</span>
          </h2>
        </div>
        {claim.documents.length === 0 ? (
          <p>No supporting documents attached.</p>
        ) : (
          claim.documents.map((document) => (
            <details
              className="document"
              key={`${document.name}-${document.type}`}
            >
              <summary>
                {document.name}
                <span>{label(document.type)}</span>
              </summary>
              <p>{document.content}</p>
            </details>
          ))
        )}
      </section>
    </>
  );
}
