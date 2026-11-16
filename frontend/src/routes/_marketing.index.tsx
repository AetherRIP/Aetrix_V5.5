import { useRef } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useScrollProgress, useScrollReveal } from '../lib/hooks'
import { AmbientField } from '../components/site/AmbientField'
import { ScoreSignal } from '../components/site/ScoreSignal'
import { useCinematicMotion } from '../components/marketing/motion'
import { Opening } from '../components/marketing/Opening'
import { Transformation } from '../components/marketing/Transformation'
import { Chapters } from '../components/marketing/Chapters'
import { Instrument } from '../components/marketing/Instrument'
import { Pipeline } from '../components/marketing/Pipeline'
import { Showcase } from '../components/marketing/Showcase'
import { Evidence } from '../components/marketing/Evidence'
import { RoleStage } from '../components/marketing/RoleStage'
import { Invitation } from '../components/marketing/Invitation'

const DESCRIPTION =
  'AI-assisted mathematics marking for Edexcel IGCSE 4MA1, built around a locked marking blueprint, transparent evidence behind every mark and human review of every uncertain answer.'

export const Route = createFileRoute('/_marketing/')({
  head: () => ({
    meta: [
      { title: 'Aetrix V5.5 — Beyond marking. Better understanding.' },
      { name: 'description', content: DESCRIPTION },
      { property: 'og:title', content: 'Aetrix V5.5 — Beyond marking. Better understanding.' },
      { property: 'og:description', content: DESCRIPTION },
      { property: 'og:type', content: 'website' },
      { name: 'twitter:card', content: 'summary_large_image' },
    ],
  }),
  component: Home,
})

/**
 * The landing page, told as five pinned acts in one scroll.
 *
 * `useCinematicMotion` owns the choreography: on a wide viewport each act is
 * pinned and its scenes transform inside one fixed stage; on a phone, with
 * motion reduced, or without JavaScript the same markup reads as five ordinary
 * chapters. The interactive sections (3D instrument, pipeline, evidence trail,
 * account types) hold their own React state, so none of them depends on an
 * animation frame to be usable.
 */
function Home() {
  const page = useRef<HTMLDivElement>(null)
  useScrollReveal()
  useScrollProgress()
  useCinematicMotion(page)

  return (
    <div className="mk" ref={page}>
      <AmbientField />

      <Opening />
      <Transformation />
      <Chapters />
      <Instrument />
      <Pipeline />
      <Showcase />
      <ScoreSignal />
      <Evidence />
      <RoleStage />
      <Invitation />
    </div>
  )
}
