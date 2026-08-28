import { useQuery } from '@tanstack/react-query'
import { getAllStories, getStory } from '@/api'
import { useAppState } from '@/state/AppStateContext'

export function useCurrentStory() {
  const { persona } = useAppState()
  return useQuery({ queryKey: ['story', persona], queryFn: () => getStory(persona) })
}

export function useAllStories() {
  return useQuery({ queryKey: ['stories'], queryFn: getAllStories })
}
