import { useQuery } from '@tanstack/react-query'
import { getPromptInjectionFixtures } from '@/api'

export function usePromptInjectionFixtures() {
  return useQuery({ queryKey: ['prompt-injection-fixtures'], queryFn: getPromptInjectionFixtures })
}
