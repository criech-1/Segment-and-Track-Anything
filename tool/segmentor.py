import torch
import cv2
import numpy as np
from sam.segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator

class Segmentor:
    def __init__(self, sam_args):
        """
        sam_args:
            sam_checkpoint: path of SAM checkpoint
            generator_args: args for everything_generator
            gpu_id: device
        """
        self.device = sam_args["gpu_id"]
        self.sam = sam_model_registry[sam_args["model_type"]](checkpoint=sam_args["sam_checkpoint"])
        self.sam.to(device=self.device)
        self.everything_generator = SamAutomaticMaskGenerator(model=self.sam, **sam_args['generator_args'])
        self.interactive_predictor = self.everything_generator.predictor
        self.have_embedded = False
        
    @torch.no_grad()
    def set_image(self, image):
        # calculate the embedding only once per frame.
        if not self.have_embedded:
            self.interactive_predictor.set_image(image)
            self.have_embedded = True
    @torch.no_grad()
    def interactive_predict(self, prompts, mode, multimask=True):
        assert self.have_embedded, 'image embedding for sam need be set before predict.'        
        
        if mode == 'point':
            masks, scores, logits = self.interactive_predictor.predict(point_coords=prompts['point_coords'], 
                                point_labels=prompts['point_modes'], 
                                multimask_output=multimask)
        elif mode == 'mask':
            masks, scores, logits = self.interactive_predictor.predict(mask_input=prompts['mask_prompt'], 
                                multimask_output=multimask)
        elif mode == 'point_mask':
            masks, scores, logits = self.interactive_predictor.predict(point_coords=prompts['point_coords'], 
                                point_labels=prompts['point_modes'], 
                                mask_input=prompts['mask_prompt'], 
                                multimask_output=multimask)
                                
        return masks, scores, logits
        
    @torch.no_grad()
    def segment_with_click(self, origin_frame, coords, modes, min_area, multimask=True):
        '''
            
            return: 
                mask: one-hot 
        '''
        self.set_image(origin_frame)

        prompts = {
            'point_coords': coords,
            'point_modes': modes,
        }
        masks, scores, logits = self.interactive_predict(prompts, 'point', multimask)

        # order scores from highest to lowest
        order = np.argsort(scores)[::-1]
        logit = np.zeros_like(logits[0])
        mask = np.zeros_like(masks[0])
        for i in order:
            if np.sum(masks[i]) > min_area:
                mask = masks[i]
                logit = logits[i, :, :]
                break
        
        # mask, logit = masks[np.argmax(scores)], logits[np.argmax(scores), :, :]
        prompts = {
            'point_coords': coords,
            'point_modes': modes,
            'mask_prompt': logit[None, :, :]
        }
        masks, scores, logits = self.interactive_predict(prompts, 'point_mask', multimask)
        # mask = masks[np.argmax(scores)]

        # order scores from highest to lowest, but take the highest one as default
        order = np.argsort(scores)[::-1]
        mask = masks[order[0]]
        for i in order:
            if np.sum(masks[i]) > min_area:
                mask = masks[i]
                break

        return mask.astype(np.uint8)

    def segment_with_box(self, origin_frame, bbox, reset_image=False):
        if reset_image:
            self.interactive_predictor.set_image(origin_frame)
        else:
            self.set_image(origin_frame)
        # coord = np.array([[int((bbox[1][0] - bbox[0][0]) / 2.),  int((bbox[1][1] - bbox[0][1]) / 2)]])
        # point_label = np.array([1])

        masks, scores, logits = self.interactive_predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.array([bbox[0][0], bbox[0][1], bbox[1][0], bbox[1][1]]),
            multimask_output=True
        )
        mask, logit = masks[np.argmax(scores)], logits[np.argmax(scores), :, :]

        masks, scores, logits = self.interactive_predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.array([[bbox[0][0], bbox[0][1], bbox[1][0], bbox[1][1]]]),
            mask_input=logit[None, :, :],
            multimask_output=True
        )
        mask = masks[np.argmax(scores)]
        
        return [mask]
