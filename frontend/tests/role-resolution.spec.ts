import { expect, test } from '@playwright/test'
import { ENGINE_ROLE, resolveRole, ROLE_META } from '../src/lib/auth/roles'

/**
 * Role precedence.
 *
 * The reported defect was the platform owner being shown as an Assistant. Two
 * independent causes are pinned here:
 *
 * 1. the shell preferred the identity provider's claim over the engine's answer,
 *    so a stale `assistant` claim outranked the verified `PLATFORM_OWNER` row;
 * 2. the engine presented `PLATFORM_OWNER` as `platform_operator`.
 *
 * These are pure checks: no page, no network, no stored session.
 */

test('the engine role outranks a stale claim', () => {
  expect(
    resolveRole({ engineResolved: true, engineRole: 'owner', claimRole: 'assistant' }),
  ).toBe('owner')
})

test('a claim cannot promote an account the engine resolved', () => {
  expect(
    resolveRole({ engineResolved: true, engineRole: 'assistant', claimRole: 'owner' }),
  ).toBe('assistant')
})

test('the claim is only a provisional hint while the engine loads', () => {
  expect(
    resolveRole({ engineResolved: false, engineRole: null, claimRole: 'owner' }),
  ).toBe('owner')
})

test('an engine answer with no recognised role is final', () => {
  expect(
    resolveRole({ engineResolved: true, engineRole: null, claimRole: 'owner' }),
  ).toBeNull()
})

test('platform ownership is the owner account type, not the administrator', () => {
  expect(ENGINE_ROLE.owner).toBe('PLATFORM_OWNER')
  expect(ENGINE_ROLE.platform_operator).toBe('ADMIN')
  expect(ROLE_META.owner.home).toBe('/platform')
  expect(ROLE_META.platform_operator.label).toBe('Platform administrator')
})

test('a workspace owner is presented as a teacher, not a platform owner', () => {
  // The engine maps OWNER -> supervisor; only PLATFORM_OWNER gets platform
  // navigation, so a workspace owner cannot be shown platform administration.
  expect(ENGINE_ROLE.supervisor).toBe('OWNER')
  expect(ROLE_META.supervisor.home).toBe('/dashboard')
})
