import { describe, expect, it } from 'vitest'
import { formatClipboardPath } from './utils.js'

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
