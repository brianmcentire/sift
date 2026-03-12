import { describe, expect, it } from 'vitest'
import { formatClipboardPath, shouldApplyOnlyDupsInSearch, parseDirQuery, dirResultToUiPath, buildUiAncestors } from './utils.js'

describe('formatClipboardPath', () => {
  it('formats windows drive paths with backslashes', () => {
    expect(formatClipboardPath('/Brian/minecraft/file.jar', 'D'))
      .toBe('D:\\Brian\\minecraft\\file.jar')
  })

  it('quotes windows paths with spaces', () => {
    expect(formatClipboardPath('/Brian (old)/minecraft/file.jar', 'D'))
      .toBe('"D:\\Brian (old)\\minecraft\\file.jar"')
  })

  it('keeps existing drive prefix and normalizes separators', () => {
    expect(formatClipboardPath('D:/Games/Minecraft/file.jar', 'D'))
      .toBe('D:\\Games\\Minecraft\\file.jar')
  })

  it('uses POSIX quoting for non-windows paths', () => {
    expect(formatClipboardPath('/Users/me/My Files/report.txt', ''))
      .toBe("'/Users/me/My Files/report.txt'")
  })
})

describe('shouldApplyOnlyDupsInSearch', () => {
  it('applies filter in normal filename search mode', () => {
    expect(shouldApplyOnlyDupsInSearch(true, { isHashResultsMode: false, subtreeDupPath: null }))
      .toBe(true)
  })

  it('bypasses filter for hash-result overlays', () => {
    expect(shouldApplyOnlyDupsInSearch(true, { isHashResultsMode: true, subtreeDupPath: null }))
      .toBe(false)
  })

  it('bypasses filter for subtree duplicate overlays', () => {
    expect(shouldApplyOnlyDupsInSearch(true, { isHashResultsMode: false, subtreeDupPath: '/x' }))
      .toBe(false)
  })

  it('bypasses filter for pinned file copies', () => {
    expect(shouldApplyOnlyDupsInSearch(true, { isHashResultsMode: false, subtreeDupPath: null, isPinnedCopiesMode: true }))
      .toBe(false)
  })

  it('does not apply when onlyDups is disabled', () => {
    expect(shouldApplyOnlyDupsInSearch(false, { isHashResultsMode: false, subtreeDupPath: null }))
      .toBe(false)
  })
})

describe('parseDirQuery', () => {
  it('parses bare query with no drive prefix', () => {
    expect(parseDirQuery('videos')).toEqual({ drive: '', pathQuery: 'videos' })
  })

  it('parses backslash drive prefix', () => {
    expect(parseDirQuery('D:\\videos')).toEqual({ drive: 'D', pathQuery: '/videos' })
  })

  it('parses forward-slash drive prefix', () => {
    expect(parseDirQuery('D:/videos')).toEqual({ drive: 'D', pathQuery: '/videos' })
  })

  it('uppercases drive letter', () => {
    expect(parseDirQuery('c:/users')).toEqual({ drive: 'C', pathQuery: '/users' })
  })

  it('handles deeper path after drive prefix', () => {
    expect(parseDirQuery('D:\\Users\\Brian\\Videos')).toEqual({ drive: 'D', pathQuery: '/Users/Brian/Videos' })
  })

  it('handles empty string', () => {
    expect(parseDirQuery('')).toEqual({ drive: '', pathQuery: '' })
  })

  it('handles single char (too short for drive prefix)', () => {
    expect(parseDirQuery('D')).toEqual({ drive: '', pathQuery: 'D' })
  })

  it('handles drive letter with colon but no slash (not a drive prefix)', () => {
    expect(parseDirQuery('D:')).toEqual({ drive: '', pathQuery: 'D:' })
  })

  it('trims whitespace', () => {
    expect(parseDirQuery('  videos  ')).toEqual({ drive: '', pathQuery: 'videos' })
  })
})

describe('dirResultToUiPath', () => {
  const multiDriveHost = new Map([['pc', { host: 'pc', drives: ['C', 'D'] }]])
  const singleDriveHost = new Map([['pc', { host: 'pc', drives: ['C'] }]])
  const posixHost = new Map([['rpi', { host: 'rpi', drives: [] }]])
  const noDrivesHost = new Map([['mac', { host: 'mac' }]])

  it('maps multi-drive host with drive to __drive__ prefix', () => {
    expect(dirResultToUiPath('pc', 'C', '/users/brian', multiDriveHost))
      .toBe('__drive__:C/users/brian')
  })

  it('maps multi-drive host with lowercase drive', () => {
    expect(dirResultToUiPath('pc', 'c', '/users/brian', multiDriveHost))
      .toBe('__drive__:C/users/brian')
  })

  it('maps single-drive host to plain path', () => {
    expect(dirResultToUiPath('pc', 'C', '/users/brian', singleDriveHost))
      .toBe('/users/brian')
  })

  it('maps POSIX host to plain path', () => {
    expect(dirResultToUiPath('rpi', '', '/home/pi', posixHost))
      .toBe('/home/pi')
  })

  it('maps host with no drives array to plain path', () => {
    expect(dirResultToUiPath('mac', '', '/Users/brian', noDrivesHost))
      .toBe('/Users/brian')
  })

  it('handles empty drive on multi-drive host', () => {
    expect(dirResultToUiPath('pc', '', '/users/brian', multiDriveHost))
      .toBe('/users/brian')
  })
})

describe('buildUiAncestors', () => {
  it('builds ancestors for plain POSIX path', () => {
    expect(buildUiAncestors('/home/pi/videos'))
      .toEqual({ ancestors: ['/home', '/home/pi'], driveNode: null })
  })

  it('builds ancestors for drive-namespaced path', () => {
    expect(buildUiAncestors('__drive__:C/users/brian'))
      .toEqual({ ancestors: ['__drive__:C', '__drive__:C/users'], driveNode: '__drive__:C' })
  })

  it('builds ancestors for deeper drive-namespaced path', () => {
    expect(buildUiAncestors('__drive__:D/users/brian/videos'))
      .toEqual({
        ancestors: ['__drive__:D', '__drive__:D/users', '__drive__:D/users/brian'],
        driveNode: '__drive__:D',
      })
  })

  it('returns empty ancestors for root-level POSIX path', () => {
    expect(buildUiAncestors('/home'))
      .toEqual({ ancestors: [], driveNode: null })
  })

  it('returns empty ancestors for bare drive node', () => {
    expect(buildUiAncestors('__drive__:C'))
      .toEqual({ ancestors: [], driveNode: null })
  })

  it('returns drive node and itself as ancestor for path one level under drive', () => {
    expect(buildUiAncestors('__drive__:C/users'))
      .toEqual({ ancestors: ['__drive__:C'], driveNode: '__drive__:C' })
  })
})
