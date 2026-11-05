import { createFileRoute } from '@tanstack/react-router'
import { useScrollReveal } from '../lib/hooks'
import { Hero } from '../components/site/Hero'
import { ProductPreview } from '../components/product/ProductPreview'
import { Workflow } from '../components/site/Workflow'
import { Features } from '../components/site/Features'
import { Security } from '../components/site/Security'
import { FinalCta } from '../components/site/FinalCta'
import { SectionHead } from '../components/site/SectionHead'

const DESCRIPTION =
  'AI-assisted mathematics marking for Edexcel IGCSE 4MA1, built around examiner-level consistency, transparent corrections and human oversight.'

export const Route = createFileRoute('/')({
  head: () => ({
    meta: [
      { title: 'Aetrix V5.5 — Mark smarter. Trust every mark.' },
      { name: 'description', content: DESCRIPTION },
      { property: 'og:title', content: 'Aetrix V5.5 — Mark smarter. Trust every mark.' },
      { property: 'og:description', content: DESCRIPTION },
      { property: 'og:type', content: 'website' },
      { name: 'twitter:card', content: 'summary_large_image' },
    ],
  }),
  component: Home,
})

function Home() {
  useScrollReveal()

  return (
    <>
      <Hero />

      <section className="section" id="platform" aria-labelledby="platform-title">
        <div className="shell">
          <SectionHead
            id="platform-title"
            title="A marking console you can read at a glance."
            note="A designed preview of the interface the rebuild is working toward: assignment state, submission progress, question-level marks and the exceptions that need a person. Every figure below is synthetic demonstration data."
          />
          <ProductPreview />
        </div>
      </section>

      <Workflow />
      <Features />
      <Security />
      <FinalCta />
    </>
  )
}
