import { test, expect, Page } from '@playwright/test';

// The Results section on a Training Event. The event and its results are stubbed at the network
// layer: a cohort with recorded answers needs deployed ranges, which an e2e run doesn't have. What
// is under test is the page -- that it shows what the API returns, and shows nothing on 403.

const EVENT_ID = '00000000-0000-4000-8000-000000000010';

const event = {
  id: EVENT_ID,
  name: 'Pilot cohort',
  start_datetime: '2026-10-06T09:00:00Z',
  is_all_day: false,
  timezone: 'UTC',
  content_ids: [],
  status: 'running',
  allowed_roles: [],
  tags: [],
  created_by_id: '00000000-0000-4000-8000-000000000001',
  created_at: '2026-10-01T09:00:00Z',
  updated_at: '2026-10-01T09:00:00Z',
  participant_count: 2,
  participants: [],
};

const results = {
  event_id: EVENT_ID,
  learners: [
    { user_id: 'u-ana', username: 'ana', completed_steps: 1, total_steps: 2, answered: 3,
      total_questions: 3, correct: 2, score_pct: 66.7, last_activity: '2026-10-06T12:00:00Z' },
    { user_id: 'u-cal', username: 'cal', completed_steps: 0, total_steps: 2, answered: 0,
      total_questions: 3, correct: 0, score_pct: null, last_activity: null },
  ],
  questions: [
    { question_id: 'q1', step_id: 's1', prompt: 'Easy one?', answered: 2, correct: 2, correct_pct: 100,
      options: [{ id: 'a', text: 'Right', correct: true, chosen: 2 }, { id: 'b', text: 'Wrong', correct: false, chosen: 0 }] },
    { question_id: 'q2', step_id: 's1', prompt: 'Hard one?', answered: 2, correct: 0, correct_pct: 0,
      options: [{ id: 'a', text: 'Tempting', correct: false, chosen: 2 }, { id: 'b', text: 'Actually right', correct: true, chosen: 0 }] },
  ],
};

// Signed in as an instructor without creating anyone: the first account registered on an instance
// becomes its admin, and later ones wait for approval, so a test that registers would either take
// over a fresh install or be unable to sign in. Every API call this file doesn't stub answers 404,
// so nothing reaches the real backend.
const instructor = {
  id: '00000000-0000-4000-8000-000000000002',
  username: 'instructor',
  email: 'instructor@example.test',
  role: 'engineer',
  roles: ['engineer'],
  tags: [],
  is_active: true,
  is_approved: true,
  password_reset_required: false,
  created_at: '2026-10-01T09:00:00Z',
};

async function signIn(page: Page) {
  await page.route('**/api/v1/**', (route) => route.fulfill({ status: 404, json: { detail: 'not stubbed' } }));
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: instructor }));
  await page.addInitScript(() => localStorage.setItem('token', 'e2e-stub-token'));
}

async function stubEvent(page: Page, resultsStatus: 200 | 403) {
  await page.route(`**/api/v1/training-events/${EVENT_ID}`, (route) =>
    route.fulfill({ json: event }));
  await page.route(`**/api/v1/training-events/${EVENT_ID}/results`, (route) =>
    resultsStatus === 200
      ? route.fulfill({ json: results })
      : route.fulfill({ status: 403, json: { detail: 'Only instructors and evaluators can see results' } }));
}

test.describe('Training Event results', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page);
  });

  test('shows learners and questions, hardest question first', async ({ page }) => {
    await stubEvent(page, 200);
    await page.goto(`/events/${EVENT_ID}`);

    const section = page.getByTestId('event-results');
    await expect(section).toBeVisible();
    await expect(section.getByText('1 of 2 students have answered')).toBeVisible();

    const learners = section.getByRole('table', { name: 'Results by learner' });
    await expect(learners.getByRole('row', { name: /ana/ })).toContainText('66.7%');
    await expect(learners.getByRole('row', { name: /cal/ })).toContainText('not started');

    const questions = section.getByRole('table', { name: 'Results by question' });
    await expect(questions.getByRole('row').first()).toContainText('Hard one?');

    await questions.getByRole('button', { name: 'Options for q2' }).click();
    await expect(questions.getByText('Tempting')).toBeVisible();
    await expect(questions.getByText('2 chose this').first()).toBeVisible();
  });

  test('shows nothing when the server says no', async ({ page }) => {
    await stubEvent(page, 403);
    const refused = page.waitForResponse(
      (r) => r.url().endsWith(`/training-events/${EVENT_ID}/results`) && r.status() === 403);
    await page.goto(`/events/${EVENT_ID}`);
    await refused;

    await expect(page.getByRole('heading', { name: /Participants/ })).toBeVisible();
    await expect(page.getByTestId('event-results')).toHaveCount(0);
  });
});
