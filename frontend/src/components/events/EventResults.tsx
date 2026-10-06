import { useState, useEffect, useCallback, Fragment } from 'react'
import { BarChart3, Download, RefreshCw, ChevronDown, ChevronRight, Check } from 'lucide-react'
import { trainingEventsApi, EventResults as Results, QuestionResult } from '../../services/api'
import { toast } from '../../stores/toastStore'
import { format, parseISO } from 'date-fns'

type LearnerSort = 'name' | 'score'

/**
 * Knowledge Check results for an event's students, read from the learner record.
 *
 * The server decides who may see this: instructors and evaluators get the results, everyone else
 * gets 403, and this section then renders nothing. Hiding it in the browser is a courtesy, not
 * the control.
 */
export function EventResults({ eventId }: { eventId: string }) {
  const [results, setResults] = useState<Results | null>(null)
  const [allowed, setAllowed] = useState(true)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [learnerSort, setLearnerSort] = useState<LearnerSort>('name')
  const [openQuestion, setOpenQuestion] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await trainingEventsApi.getResults(eventId)
      setResults(response.data)
      setAllowed(true)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) setAllowed(false)
      else toast.error('Could not load results')
    } finally {
      setLoading(false)
    }
  }, [eventId])

  useEffect(() => {
    load()
  }, [load])

  const exportCsv = async () => {
    setExporting(true)
    try {
      const response = await trainingEventsApi.exportResultsCsv(eventId)
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `event-${eventId}-results.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Could not export results')
    } finally {
      setExporting(false)
    }
  }

  if (!allowed) return null

  const learners = [...(results?.learners ?? [])].sort((a, b) =>
    learnerSort === 'score'
      ? (b.score_pct ?? -1) - (a.score_pct ?? -1)
      : (a.username ?? '').localeCompare(b.username ?? '')
  )
  // Hardest first: the question a cohort misses most is the one to look at.
  const questions = [...(results?.questions ?? [])].sort(
    (a, b) => (a.correct_pct ?? 101) - (b.correct_pct ?? 101)
  )
  const answeredAny = learners.filter((l) => l.answered > 0)
  const averageScore = answeredAny.length
    ? Math.round(answeredAny.reduce((sum, l) => sum + (l.score_pct ?? 0), 0) / answeredAny.length)
    : null

  return (
    <div className="bg-white shadow rounded-lg p-6" data-testid="event-results">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-900">
          <BarChart3 className="inline h-4 w-4 mr-1" />
          Results
        </h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center px-3 py-1.5 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={exportCsv}
            disabled={exporting || !results?.learners.length}
            className="inline-flex items-center px-3 py-1.5 text-sm text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-50"
          >
            <Download className="h-4 w-4 mr-1" />
            Export CSV
          </button>
        </div>
      </div>

      {loading && !results ? (
        <p className="text-sm text-gray-500">Loading results…</p>
      ) : !learners.length ? (
        <p className="text-sm text-gray-500">
          No students in this event yet. Results appear here as students answer Knowledge Checks.
        </p>
      ) : (
        <div className="space-y-6">
          <p className="text-sm text-gray-600">
            {answeredAny.length} of {learners.length} students have answered
            {averageScore !== null && <> · average score {averageScore}%</>}
          </p>

          <div className="overflow-x-auto">
            <table className="min-w-full text-sm" aria-label="Results by learner">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
                  <th className="py-2 pr-4">
                    <button type="button" onClick={() => setLearnerSort('name')} className="uppercase">
                      Learner{learnerSort === 'name' && ' ↓'}
                    </button>
                  </th>
                  <th className="py-2 pr-4">Steps</th>
                  <th className="py-2 pr-4">Answered</th>
                  <th className="py-2 pr-4">Correct</th>
                  <th className="py-2 pr-4">
                    <button type="button" onClick={() => setLearnerSort('score')} className="uppercase">
                      Score{learnerSort === 'score' && ' ↓'}
                    </button>
                  </th>
                  <th className="py-2">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {learners.map((l) => (
                  <tr key={l.user_id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium text-gray-900">{l.username}</td>
                    <td className="py-2 pr-4 tabular-nums">
                      {l.completed_steps}/{l.total_steps}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {l.answered}/{l.total_questions}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">{l.correct}</td>
                    <td className="py-2 pr-4 tabular-nums">
                      {l.score_pct === null ? <span className="text-gray-400">not started</span> : `${l.score_pct}%`}
                    </td>
                    <td className="py-2 text-gray-500">
                      {l.last_activity ? format(parseISO(l.last_activity), 'MMM d, HH:mm') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {questions.length > 0 && (
            <div className="overflow-x-auto">
              <h4 className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-2">
                Questions, hardest first
              </h4>
              <table className="min-w-full text-sm" aria-label="Results by question">
                <tbody>
                  {questions.map((q) => (
                    <QuestionRow
                      key={q.question_id}
                      question={q}
                      open={openQuestion === q.question_id}
                      onToggle={() => setOpenQuestion(openQuestion === q.question_id ? null : q.question_id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function QuestionRow({ question: q, open, onToggle }: { question: QuestionResult; open: boolean; onToggle: () => void }) {
  const pct = q.correct_pct
  const tone = pct === null ? 'bg-gray-200' : pct < 50 ? 'bg-red-500' : pct < 80 ? 'bg-amber-500' : 'bg-green-500'
  return (
    <Fragment>
      <tr className="border-b align-top">
        <td className="py-2 pr-2 w-6">
          <button type="button" onClick={onToggle} aria-expanded={open} aria-label={`Options for ${q.question_id}`}>
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </td>
        <td className="py-2 pr-4">
          <div className="text-gray-900">{q.prompt ?? q.question_id}</div>
          <div className="text-xs text-gray-500">
            {q.question_id}
            {q.step_id && <> · step {q.step_id}</>}
          </div>
        </td>
        <td className="py-2 pr-4 tabular-nums text-gray-600 whitespace-nowrap">{q.answered} answered</td>
        <td className="py-2 w-48">
          <div className="flex items-center gap-2">
            <div className="h-2 flex-1 rounded bg-gray-100" aria-hidden="true">
              <div className={`h-2 rounded ${tone}`} style={{ width: `${pct ?? 0}%` }} />
            </div>
            <span className="tabular-nums w-12 text-right">{pct === null ? '—' : `${pct}%`}</span>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="border-b bg-gray-50">
          <td />
          <td colSpan={3} className="py-2 pr-4">
            <ul className="space-y-1">
              {q.options.map((o) => (
                <li key={o.id} className="flex items-center gap-2">
                  <span className="w-5">{o.correct && <Check className="h-4 w-4 text-green-600" aria-label="correct answer" />}</span>
                  <span className="flex-1">{o.text ?? o.id}</span>
                  <span className="tabular-nums text-gray-600">
                    {o.chosen} chose this
                  </span>
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </Fragment>
  )
}
