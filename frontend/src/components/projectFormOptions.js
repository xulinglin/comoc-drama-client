export const PROJECT_STYLE_GROUPS = [
  { label: '3D国漫', options: [
    { label: '修仙玄幻', value: '3d-xiuxian', desc: '3D国漫修仙玄幻场景设计，东方仙侠世界观，仙府楼阁、悬空仙山、丹药法宝、飞剑御空、渡劫天雷，超写实3D场景模型，UE5虚幻引擎渲染，8K超高清，电影级场景设计，物理级布料与流体模拟，PBR材质，全局光照，体积光，柔和电影光影，国风玄幻美术风格，仙侠游戏CG，高级低饱和色调，细节丰富，虚幻引擎5渲染效果，无文字，无水印' },
    { label: '武侠', value: '3d-wuxia', desc: '3D国漫武侠场景设计，东方江湖世界观，竹林古寺、飞檐客栈、雨夜长街、刀光剑影、内力气劲，超写实3D场景模型，UE5虚幻引擎渲染，8K超高清，电影级场景设计，物理级布料与粒子模拟，PBR材质，全局光照，体积光，柔和电影光影，国风武侠美术风格，武侠游戏CG，高级低饱和色调，细节丰富，虚幻引擎5渲染效果，无文字，无水印' },
    { label: '神话', value: '3d-myth', desc: '3D国漫神话场景设计，上古洪荒世界观，天宫瑶池、神兽异种、封神战场、法宝神通、混沌星河，超写实3D场景模型，UE5虚幻引擎渲染，8K超高清，电影级场景设计，物理级粒子与光效模拟，PBR材质，全局光照，体积光，恢弘史诗光影，国风神话美术风格，神话游戏CG，高级低饱和色调，细节丰富，虚幻引擎5渲染效果，无文字，无水印' },
  ] },
  { label: '真人写实', options: [
    { label: '都市', value: 'real-urban', desc: '真人写实摄影风格，电影级画质。现代都市，摩天大楼、霓虹夜景、职场穿搭、豪车公寓，自然光影，4K，高细节。' },
    { label: '年代', value: 'real-era', desc: '真人写实摄影风格，电影级画质。年代复古，老街巷弄、旗袍中山装、搪瓷茶缸、绿皮火车，怀旧暖色调，4K，高细节。' },
    { label: '悬疑', value: 'real-mystery', desc: '真人写实摄影风格，电影级画质。悬疑推理，雨夜暗巷、老旧档案室、微光手电、蛛丝马迹，冷色调暗黑氛围，4K，高细节。' },
    { label: '重生', value: 'real-rebirth', desc: '真人写实摄影风格，电影级画质。重生逆袭，校园重聚、商战博弈、时空交错闪回，情感细腻光影，4K，高细节。' },
  ] },
  { label: '二次元', options: [
    { label: '校园', value: 'anime-school', desc: '二次元动画风格，日系赛璐璐上色。青春校园，教室走廊、樱花操场、制服书包、社团活动，明亮通透色调，高细节。' },
    { label: '异世界', value: 'anime-isekai', desc: '二次元动画风格，日系赛璐璐上色。异世界冒险，魔法阵、精灵兽、古城遗迹、技能特效，奇幻绚丽色彩，高细节。' },
    { label: '恋爱', value: 'anime-romance', desc: '二次元动画风格，日系赛璐璐上色。恋爱日常，咖啡馆、天台夕阳、烟花祭典、牵手奔跑，柔和唯美画风，高细节。' },
    { label: '热血', value: 'anime-action', desc: '二次元动画风格，日系赛璐璐上色。热血战斗，能量爆发、速度线、技能对轰、废墟硝烟，动态强对比光影，高细节。' },
  ] },
  { label: 'Q版', options: [
    { label: '萌宠', value: 'chibi-pet', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。萌宠日常，毛茸茸质感、爪子肉垫、歪头杀、打滚撒娇，明亮饱和色调，高细节。' },
    { label: '搞笑', value: 'chibi-comedy', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。搞笑沙雕，夸张表情包、翻白眼、石化裂开、汗滴特效，趣味撞色画风，高细节。' },
    { label: '儿童', value: 'chibi-kids', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。儿童故事，积木玩具、彩虹气球、动物朋友、睡前故事，温馨柔和色调，高细节。' },
    { label: '轻喜剧', value: 'chibi-sitcom', desc: 'Q版3D卡通风格，可爱圆润造型，大眼短肢比例。轻松喜剧，办公室摸鱼、外卖日常、室友互怼、猫狗大战，柔和明快画风，高细节。' },
  ] },
]

export const PROJECT_RATIO_OPTIONS = [
  { label: '21:9', value: '21:9', shape: 'ultrawide' },
  { label: '16:9', value: '16:9', shape: 'landscape' },
  { label: '4:3', value: '4:3', shape: 'classic' },
  { label: '1:1', value: '1:1', shape: 'square' },
  { label: '3:4', value: '3:4', shape: 'portrait3' },
  { label: '9:16', value: '9:16', shape: 'portrait9' },
]

export function getProjectStyleDescription(style) {
  for (const group of PROJECT_STYLE_GROUPS) {
    const option = group.options.find(item => item.value === style)
    if (option) return option.desc
  }
  if (style === '3d-xuanhuan') {
    return '3D数字渲染，虚幻引擎5级画质，高精度CG动画风格。修仙玄幻，写实仙侠，仙府楼阁、丹药法宝、飞剑御空、渡劫天雷，东方修真世界观，电影级光影，4K，高细节。'
  }
  return ''
}
