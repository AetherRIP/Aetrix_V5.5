/** A section header: the heading states the idea, the note states the limit. */
export function SectionHead({
  title,
  note,
  id,
}: {
  title: string
  note: string
  id?: string
}) {
  return (
    <div className="section-head" data-reveal>
      <h2 className="section-head__title" id={id}>
        {title}
      </h2>
      <p className="section-head__note">{note}</p>
    </div>
  )
}
