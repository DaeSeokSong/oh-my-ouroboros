// Claude Code 테마 값이 light 로 시작하면 밝은 팔레트, 그 밖(dark·daltonized·auto·읽기 실패)은 어두운 팔레트.
export const themeKind = v => (typeof v === 'string' && v.startsWith('light') ? 'light' : 'dark')
