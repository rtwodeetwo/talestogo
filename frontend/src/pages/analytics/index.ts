/**
 * Barrel export for all analytics pages.
 *
 * This allows imports like:
 *   import { BrandMentions, SentimentAnalysis, ShareOfVoice } from '@/pages/analytics'
 *
 * Instead of:
 *   import BrandMentions from '@/pages/analytics/BrandMentions'
 *   import SentimentAnalysis from '@/pages/analytics/SentimentAnalysis'
 *   import ShareOfVoice from '@/pages/analytics/ShareOfVoice'
 */

export { default as BrandMentions } from './BrandMentions';
export { default as CompetitorThreats } from './CompetitorThreats';
export { default as DescriptorAnalysis } from './DescriptorAnalysis';
export { default as Investigations } from './Investigations';
export { default as PositioningAnalysis } from './PositioningAnalysis';
export { default as SentimentAnalysis } from './SentimentAnalysis';
export { default as ShareOfVoice } from './ShareOfVoice';
export { default as StrategicPriorities } from './StrategicPriorities';
