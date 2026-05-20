export interface TypewriterOptions {
  onUpdate?: () => void
  isActive?: () => boolean
  minDurationMs?: number
  maxDurationMs?: number
}

function nextFrame(): Promise<number> {
  return new Promise(resolve => requestAnimationFrame(resolve))
}

export async function typewriterReveal(
  target: { content: string },
  fullText: string,
  options: TypewriterOptions = {}
): Promise<void> {
  const currentText = target.content || ''
  const startText = fullText.startsWith(currentText) ? currentText : ''

  if (target.content !== startText) {
    target.content = startText
  }

  if (!fullText || startText === fullText) {
    target.content = fullText
    options.onUpdate?.()
    return
  }

  const remainingLength = fullText.length - startText.length
  const duration = Math.min(
    options.maxDurationMs ?? 1400,
    Math.max(options.minDurationMs ?? 300, remainingLength * 8)
  )
  const startTime = performance.now()

  while (true) {
    if (options.isActive && !options.isActive()) {
      return
    }

    const elapsed = performance.now() - startTime
    const progress = Math.min(1, elapsed / duration)
    const nextLength = startText.length + Math.max(1, Math.floor(remainingLength * progress))

    target.content = fullText.slice(0, Math.min(fullText.length, nextLength))
    options.onUpdate?.()

    if (progress >= 1) {
      break
    }

    await nextFrame()
  }

  target.content = fullText
  options.onUpdate?.()
}
